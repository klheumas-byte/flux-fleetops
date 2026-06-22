import { useState } from 'react';
import {
  User,
  Phone,
  Mail,
  MapPin,
  Calendar,
  CreditCard,
  CheckCircle,
  XCircle,
  AlertCircle,
  FileText,
  Shield,
  Users,
  DollarSign,
  Download,
  Eye,
  ArrowLeft,
  Check,
  X,
  Clock,
  IdCard,
  Car
} from 'lucide-react';

export default function DriverApproval() {
  const [qualificationChecks, setQualificationChecks] = useState({
    ghanaCardVerified: true,
    validLicense: true,
    minimumExperience: true,
    canDriveManual: true,
    canDriveAutomatic: false,
    depositPaid: true,
    guarantorApproved: false,
  });

  const [approvalNotes, setApprovalNotes] = useState('');

  const driver = {
    id: 7,
    name: 'Samuel Amoah',
    photo: null,
    dateOfBirth: '1990-03-15',
    age: 36,
    ghanaCardNumber: 'GHA-123456789-0',
    phone: '+233 24 789 0123',
    email: 'samuel.amoah@email.com',
    address: 'House No. 45, Madina Estate, Accra, Ghana',
    emergencyContact: {
      name: 'Sarah Amoah',
      relationship: 'Wife',
      phone: '+233 24 789 0124'
    },
    applicationDate: '2026-06-01',
    license: {
      number: 'DL-987654321',
      issueDate: '2020-05-10',
      expiryDate: '2028-05-10',
      class: 'B, C',
      yearsExperience: 6,
      previousViolations: 0
    },
    guarantor: {
      name: 'Kwame Mensah',
      relationship: 'Brother',
      phone: '+233 24 555 1234',
      email: 'kwame.mensah@email.com',
      address: 'House No. 12, Tesano, Accra, Ghana',
      ghanaCardNumber: 'GHA-987654321-0',
      occupation: 'Civil Servant',
      employer: 'Ghana Revenue Authority',
      verified: false,
      verificationDate: null
    },
    deposit: {
      amount: 5000,
      paymentMethod: 'Mobile Money',
      referenceNumber: 'MM-2026-060100123',
      paymentDate: '2026-06-01',
      receiptUrl: '#',
      verified: true
    },
    documents: [
      { name: 'Ghana Card (Front)', status: 'verified', uploadDate: '2026-06-01' },
      { name: 'Ghana Card (Back)', status: 'verified', uploadDate: '2026-06-01' },
      { name: 'Driver License (Front)', status: 'verified', uploadDate: '2026-06-01' },
      { name: 'Driver License (Back)', status: 'verified', uploadDate: '2026-06-01' },
      { name: 'Passport Photo', status: 'verified', uploadDate: '2026-06-01' },
      { name: 'Guarantor Ghana Card', status: 'pending', uploadDate: '2026-06-01' },
      { name: 'Deposit Receipt', status: 'verified', uploadDate: '2026-06-01' },
    ]
  };

  const allQualificationsMet = Object.values(qualificationChecks).every(check => check === true);

  const toggleCheck = (key: string) => {
    setQualificationChecks(prev => ({
      ...prev,
      [key]: !prev[key as keyof typeof prev]
    }));
  };

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Driver Approval</h1>
            <p className="text-gray-500 mt-1">Review and approve driver application</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-3 py-1.5 bg-yellow-100 text-yellow-800 rounded-lg text-sm font-medium flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Pending Review
          </span>
          <span className="text-sm text-gray-500">Applied: {driver.applicationDate}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          {/* Personal Information */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="bg-gradient-to-r from-blue-600 to-purple-600 p-6">
              <div className="flex items-start gap-4">
                <div className="w-20 h-20 bg-white rounded-full flex items-center justify-center text-2xl font-semibold text-blue-600">
                  {driver.name.split(' ').map(n => n[0]).join('')}
                </div>
                <div className="flex-1 text-white">
                  <h2 className="text-2xl font-semibold">{driver.name}</h2>
                  <div className="grid grid-cols-2 gap-4 mt-4">
                    <div className="flex items-center gap-2">
                      <Phone className="w-4 h-4" />
                      <span className="text-sm">{driver.phone}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Mail className="w-4 h-4" />
                      <span className="text-sm">{driver.email}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="p-6 space-y-4">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <User className="w-5 h-5 text-blue-600" />
                Personal Information
              </h3>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-gray-500">Date of Birth</label>
                  <div className="flex items-center gap-2 mt-1">
                    <Calendar className="w-4 h-4 text-gray-400" />
                    <span className="text-sm font-medium text-gray-900">{driver.dateOfBirth}</span>
                    <span className="text-sm text-gray-500">({driver.age} years)</span>
                  </div>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Ghana Card Number</label>
                  <div className="flex items-center gap-2 mt-1">
                    <IdCard className="w-4 h-4 text-gray-400" />
                    <span className="text-sm font-medium text-gray-900">{driver.ghanaCardNumber}</span>
                    <CheckCircle className="w-4 h-4 text-green-600" />
                  </div>
                </div>
              </div>

              <div>
                <label className="text-sm text-gray-500">Residential Address</label>
                <div className="flex items-center gap-2 mt-1">
                  <MapPin className="w-4 h-4 text-gray-400" />
                  <span className="text-sm font-medium text-gray-900">{driver.address}</span>
                </div>
              </div>

              <div className="pt-4 border-t border-gray-200">
                <h4 className="text-sm font-semibold text-gray-900 mb-3">Emergency Contact</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm text-gray-500">Name</label>
                    <p className="text-sm font-medium text-gray-900 mt-1">{driver.emergencyContact.name}</p>
                  </div>
                  <div>
                    <label className="text-sm text-gray-500">Relationship</label>
                    <p className="text-sm font-medium text-gray-900 mt-1">{driver.emergencyContact.relationship}</p>
                  </div>
                  <div>
                    <label className="text-sm text-gray-500">Phone Number</label>
                    <p className="text-sm font-medium text-gray-900 mt-1">{driver.emergencyContact.phone}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Driver License Verification */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-4">
              <Shield className="w-5 h-5 text-blue-600" />
              Driver License Verification
            </h3>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-gray-500">License Number</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.license.number}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">License Class</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.license.class}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Issue Date</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.license.issueDate}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Expiry Date</label>
                  <div className="flex items-center gap-2 mt-1">
                    <p className="text-sm font-medium text-green-600">{driver.license.expiryDate}</p>
                    <CheckCircle className="w-4 h-4 text-green-600" />
                  </div>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Years of Experience</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.license.yearsExperience} years</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Previous Violations</label>
                  <p className="text-sm font-medium text-green-600 mt-1">
                    {driver.license.previousViolations} violations
                  </p>
                </div>
              </div>

              <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-green-600 mt-0.5" />
                <div>
                  <h4 className="text-sm font-semibold text-green-900">License Verified</h4>
                  <p className="text-sm text-green-700 mt-1">Driver license has been verified with DVLA database.</p>
                </div>
              </div>
            </div>
          </div>

          {/* Guarantor Verification */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-4">
              <Users className="w-5 h-5 text-blue-600" />
              Guarantor Verification
            </h3>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-gray-500">Guarantor Name</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.name}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Relationship</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.relationship}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Phone Number</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.phone}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Email</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.email}</p>
                </div>
                <div className="col-span-2">
                  <label className="text-sm text-gray-500">Address</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.address}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Ghana Card Number</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.ghanaCardNumber}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Occupation</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.occupation}</p>
                </div>
                <div className="col-span-2">
                  <label className="text-sm text-gray-500">Employer</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.guarantor.employer}</p>
                </div>
              </div>

              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-yellow-600 mt-0.5" />
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-yellow-900">Guarantor Verification Pending</h4>
                  <p className="text-sm text-yellow-700 mt-1">Contact guarantor to verify information and relationship.</p>
                </div>
                <button className="px-3 py-1.5 bg-yellow-600 text-white rounded-lg text-sm font-medium hover:bg-yellow-700">
                  Call Guarantor
                </button>
              </div>
            </div>
          </div>

          {/* Deposit Information */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-4">
              <DollarSign className="w-5 h-5 text-blue-600" />
              Deposit Information
            </h3>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-gray-500">Deposit Amount</label>
                  <p className="text-2xl font-semibold text-gray-900 mt-1">GH₵ {driver.deposit.amount.toLocaleString()}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Payment Method</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.deposit.paymentMethod}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Reference Number</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.deposit.referenceNumber}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">Payment Date</label>
                  <p className="text-sm font-medium text-gray-900 mt-1">{driver.deposit.paymentDate}</p>
                </div>
              </div>

              <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
                <CheckCircle className="w-5 h-5 text-green-600 mt-0.5" />
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-green-900">Deposit Verified</h4>
                  <p className="text-sm text-green-700 mt-1">Payment has been confirmed and credited to account.</p>
                </div>
                <button className="flex items-center gap-2 px-3 py-1.5 bg-white border border-green-300 rounded-lg text-sm font-medium text-green-700 hover:bg-green-50">
                  <Download className="w-4 h-4" />
                  Receipt
                </button>
              </div>
            </div>
          </div>

          {/* Documents */}
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-blue-600" />
              Submitted Documents
            </h3>

            <div className="space-y-2">
              {driver.documents.map((doc, index) => (
                <div key={index} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                  <div className="flex items-center gap-3">
                    <FileText className="w-5 h-5 text-gray-400" />
                    <div>
                      <p className="text-sm font-medium text-gray-900">{doc.name}</p>
                      <p className="text-xs text-gray-500">Uploaded: {doc.uploadDate}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {doc.status === 'verified' ? (
                      <span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs font-medium flex items-center gap-1">
                        <CheckCircle className="w-3 h-3" />
                        Verified
                      </span>
                    ) : (
                      <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded text-xs font-medium flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        Pending
                      </span>
                    )}
                    <button className="p-2 hover:bg-gray-200 rounded-lg">
                      <Eye className="w-4 h-4 text-gray-600" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Sidebar - Qualification Checklist */}
        <div className="lg:col-span-1">
          <div className="sticky top-6 space-y-6">
            {/* Qualification Checklist */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-900 mb-4">Qualification Checklist</h3>

              <div className="space-y-3">
                <button
                  onClick={() => toggleCheck('ghanaCardVerified')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.ghanaCardVerified
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Ghana Card Verified</span>
                  {qualificationChecks.ghanaCardVerified ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>

                <button
                  onClick={() => toggleCheck('validLicense')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.validLicense
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Valid License</span>
                  {qualificationChecks.validLicense ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>

                <button
                  onClick={() => toggleCheck('minimumExperience')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.minimumExperience
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Min. 2 Years Experience</span>
                  {qualificationChecks.minimumExperience ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>

                <button
                  onClick={() => toggleCheck('canDriveManual')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.canDriveManual
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Can Drive Manual</span>
                  {qualificationChecks.canDriveManual ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>

                <button
                  onClick={() => toggleCheck('canDriveAutomatic')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.canDriveAutomatic
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Can Drive Automatic</span>
                  {qualificationChecks.canDriveAutomatic ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>

                <button
                  onClick={() => toggleCheck('depositPaid')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.depositPaid
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Deposit Paid</span>
                  {qualificationChecks.depositPaid ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>

                <button
                  onClick={() => toggleCheck('guarantorApproved')}
                  className={`w-full flex items-center justify-between p-3 rounded-lg border-2 transition-all ${
                    qualificationChecks.guarantorApproved
                      ? 'bg-green-50 border-green-500'
                      : 'bg-gray-50 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-sm font-medium text-gray-900">Guarantor Approved</span>
                  {qualificationChecks.guarantorApproved ? (
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  ) : (
                    <XCircle className="w-5 h-5 text-gray-400" />
                  )}
                </button>
              </div>

              {/* Progress */}
              <div className="mt-6 pt-6 border-t border-gray-200">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-700">Completion</span>
                  <span className="text-sm font-semibold text-gray-900">
                    {Object.values(qualificationChecks).filter(v => v).length} / {Object.keys(qualificationChecks).length}
                  </span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all ${
                      allQualificationsMet ? 'bg-green-500' : 'bg-blue-500'
                    }`}
                    style={{
                      width: `${(Object.values(qualificationChecks).filter(v => v).length / Object.keys(qualificationChecks).length) * 100}%`
                    }}
                  ></div>
                </div>
              </div>

              {allQualificationsMet && (
                <div className="mt-4 bg-green-50 border border-green-200 rounded-lg p-3 flex items-center gap-2">
                  <CheckCircle className="w-5 h-5 text-green-600" />
                  <span className="text-sm font-medium text-green-900">All requirements met!</span>
                </div>
              )}
            </div>

            {/* Approval Notes */}
            <div className="bg-white rounded-lg border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-900 mb-4">Approval Notes</h3>
              <textarea
                value={approvalNotes}
                onChange={(e) => setApprovalNotes(e.target.value)}
                placeholder="Add notes about this approval decision..."
                className="w-full h-32 p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent resize-none text-sm"
              ></textarea>
            </div>

            {/* Action Buttons */}
            <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-3">
              <button
                disabled={!allQualificationsMet}
                className={`w-full py-3 px-4 rounded-lg font-medium flex items-center justify-center gap-2 transition-all ${
                  allQualificationsMet
                    ? 'bg-green-600 text-white hover:bg-green-700'
                    : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                }`}
              >
                <Check className="w-5 h-5" />
                Approve Driver
              </button>

              <button className="w-full py-3 px-4 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 flex items-center justify-center gap-2">
                <X className="w-5 h-5" />
                Reject Application
              </button>

              <button className="w-full py-3 px-4 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 flex items-center justify-center gap-2">
                <AlertCircle className="w-5 h-5" />
                Request More Info
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
